#include <algorithm>

#include "outer_update_runtime_domain.hpp"

namespace qebs {

namespace {

std::string outer_update_prefix(const std::string& software_family,
                                const std::string& flow_family) {
    if (software_family == "CP2K" && flow_family == "QS_OT") {
        return "cp2k_ot";
    }
    if (software_family == "CP2K") {
        return "cp2k";
    }
    if (software_family == "VASP" && flow_family == "FAST") {
        return "vasp_fast";
    }
    if (software_family == "VASP") {
        return "vasp";
    }
    return "qe";
}

std::string density_output_handle(const Body04StageRequest& request) {
    const auto prefix =
        outer_update_prefix(request.software_family, request.flow_family);
    return prefix + "_rho_iter_" +
           std::to_string(request.phase_b_summary.config.scf_iteration);
}

std::string potential_output_handle(const Body04StageRequest& request) {
    const auto prefix =
        outer_update_prefix(request.software_family, request.flow_family);
    return prefix + "_veff_iter_" +
           std::to_string(request.phase_b_summary.config.scf_iteration);
}

std::string mixing_output_handle(const Body04StageRequest& request) {
    const auto prefix =
        outer_update_prefix(request.software_family, request.flow_family);
    return prefix + "_rho_mixed_iter_" +
           std::to_string(request.phase_b_summary.config.scf_iteration);
}

struct Body04LeafSpec {
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

Body04LeafSpec make_body04_leaf_spec(const std::string& stage_name,
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
    Body04LeafSpec spec;
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

void refresh_body04_flow_control(Body04FlowControlSummary& flow_control) {
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
        flow_control.dominant_backpressure_route = "BODY_04_ISSUE";
    }
}

Body04FlowControlSummary simulate_body04_pipeline(
    const std::vector<Body04LeafSpec>& specs,
    int work_items,
    int issue_credit_limit,
    const std::string& source_route_name) {
    Body04FlowControlSummary summary;
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
    source_route.source_stage = "BODY_04_ISSUE_WINDOW";
    source_route.sink_stage = specs.front().stage_name;
    source_route.arbitration_domain = "BODY_04_ISSUE_WINDOW";
    summary.routes.push_back(source_route);

    for (std::size_t spec_id = 0; spec_id < specs.size(); ++spec_id) {
        const auto& spec = specs[spec_id];
        RouteBackpressureSummary route;
        route.route_name = spec.route_name;
        route.cause = spec.route_cause;
        route.source_stage = spec.stage_name;
        route.sink_stage = spec_id + 1 < specs.size()
                               ? specs[spec_id + 1].stage_name
                               : std::string("BODY_04_STAGE_COMMIT");
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
                    } else if (queue_occupancy[stage_id + 1] <
                               specs[stage_id + 1].ingress_queue_depth) {
                        queue_occupancy[stage_id + 1] += 1;
                        summary.stages[stage_id + 1].accept_count += 1;
                        if (queue_occupancy[stage_id + 1] >
                            summary.stages[stage_id + 1].max_queue_occupancy) {
                            summary.stages[stage_id + 1].max_queue_occupancy =
                                queue_occupancy[stage_id + 1];
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
                summary.issue_stall_ref_cycles += 1;
                summary.routes.front().stall_ref_cycles += 1;
                summary.routes.front().conflict_count += 1;
            }
        }
    }

    summary.stage_complete_count = 1;
    refresh_body04_flow_control(summary);
    return summary;
}

void refresh_body04_bundle_summary(Body04BundleSummary& summary) {
    summary.total_ref_cycles = summary.density_stage.total_ref_cycles +
                               summary.potential_stage.total_ref_cycles +
                               summary.mixing_stage.total_ref_cycles;
    summary.total_backpressure_ref_cycles =
        summary.density_stage.flow_control.total_backpressure_ref_cycles +
        summary.potential_stage.flow_control.total_backpressure_ref_cycles +
        summary.mixing_stage.flow_control.total_backpressure_ref_cycles;

    summary.critical_stage_kind = summary.density_stage.stage_kind;
    if (summary.potential_stage.total_ref_cycles > summary.density_stage.total_ref_cycles &&
        summary.potential_stage.total_ref_cycles >= summary.mixing_stage.total_ref_cycles) {
        summary.critical_stage_kind = summary.potential_stage.stage_kind;
    } else if (summary.mixing_stage.total_ref_cycles >
               std::max(summary.density_stage.total_ref_cycles,
                        summary.potential_stage.total_ref_cycles)) {
        summary.critical_stage_kind = summary.mixing_stage.stage_kind;
    }

    summary.dominant_backpressure_stage_kind = "NONE";
    int dominant_bp_cycles = 0;
    if (summary.density_stage.flow_control.total_backpressure_ref_cycles > dominant_bp_cycles) {
        dominant_bp_cycles = summary.density_stage.flow_control.total_backpressure_ref_cycles;
        summary.dominant_backpressure_stage_kind = summary.density_stage.stage_kind;
    }
    if (summary.potential_stage.flow_control.total_backpressure_ref_cycles >
        dominant_bp_cycles) {
        dominant_bp_cycles = summary.potential_stage.flow_control.total_backpressure_ref_cycles;
        summary.dominant_backpressure_stage_kind = summary.potential_stage.stage_kind;
    }
    if (summary.mixing_stage.flow_control.total_backpressure_ref_cycles > dominant_bp_cycles) {
        summary.dominant_backpressure_stage_kind = summary.mixing_stage.stage_kind;
    }
}

void log_body04_stage_details(const char* module_name,
                              const Body04StageSummary& stage) {
    log_line(module_name, "BODY_04 stage summary => " + stage.brief());
    log_line(module_name,
             "BODY_04 stage flow-control => " + stage.flow_control.brief());
    for (const auto& occupancy : stage.unit_occupancy) {
        log_line(module_name, "BODY_04 unit occupancy => " + occupancy.brief());
    }
    for (const auto& flow_stage : stage.flow_control.stages) {
        log_line(module_name, "BODY_04 flow stage => " + flow_stage.brief());
    }
    for (const auto& route : stage.flow_control.routes) {
        log_line(module_name, "BODY_04 backpressure route => " + route.brief());
    }
}

}  // namespace

OuterUpdateRuntimeDomain::OuterUpdateRuntimeDomain(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      density_stage_(sc_core::sc_module_name("density_accumulation_stage")),
      potential_stage_(sc_core::sc_module_name("potential_refresh_stage")),
      mixing_stage_(sc_core::sc_module_name("mixing_convergence_stage")) {}

Body04StageRequest OuterUpdateRuntimeDomain::make_density_request(
    const Body04BundleRequest& request) const {
    Body04StageRequest stage;
    stage.bundle_id = request.bundle_id;
    stage.stage_kind = "BODY_04A_DENSITY_ACCUM";
    stage.software_family = request.software_family;
    stage.flow_family = request.flow_family;
    stage.incoming_state = request.incoming_state;
    stage.phase_b_summary = request.phase_b_summary;
    stage.primary_input_object = request.incoming_state.wave_object;
    stage.secondary_input_object = request.incoming_state.density_object;
    stage.completion_mode = "SYNC";
    stage.join_mode = "HARD_BARRIER";
    return stage;
}

Body04StageRequest OuterUpdateRuntimeDomain::make_potential_request(
    const Body04BundleRequest& request, const DensitySummary& density) const {
    Body04StageRequest stage;
    stage.bundle_id = request.bundle_id;
    stage.stage_kind = "BODY_04B_POTENTIAL_REFRESH";
    stage.software_family = request.software_family;
    stage.flow_family = request.flow_family;
    stage.incoming_state = request.incoming_state;
    stage.phase_b_summary = request.phase_b_summary;
    stage.primary_input_object = density.density_object;
    stage.secondary_input_object = request.incoming_state.projector_object;
    stage.completion_mode = "SYNC";
    stage.join_mode = "HARD_BARRIER";
    return stage;
}

Body04StageRequest OuterUpdateRuntimeDomain::make_mixing_request(
    const Body04BundleRequest& request, const DensitySummary& density,
    const PotentialSummary& potential) const {
    Body04StageRequest stage;
    stage.bundle_id = request.bundle_id;
    stage.stage_kind = "BODY_04C_MIX_CONVERGE";
    stage.software_family = request.software_family;
    stage.flow_family = request.flow_family;
    stage.incoming_state = request.incoming_state;
    stage.phase_b_summary = request.phase_b_summary;
    stage.primary_input_object = density.density_object;
    stage.secondary_input_object = potential.potential_object;
    stage.completion_mode = "QUERYABLE";
    stage.join_mode = "SOFT_JOIN";
    return stage;
}

Body04StageDescriptor OuterUpdateRuntimeDomain::make_stage_descriptor(
    const Body04StageRequest& request,
    const std::string& expected_output_handle) const {
    Body04StageDescriptor descriptor;
    descriptor.stage_kind = request.stage_kind;
    descriptor.primary_input_handle = request.primary_input_object.object_handle;
    descriptor.secondary_input_handle = request.secondary_input_object.object_handle;
    descriptor.expected_output_handle = expected_output_handle;

    if (request.stage_kind == "BODY_04A_DENSITY_ACCUM") {
        descriptor.execution_domain = "OUTER_UPDATE_RUNTIME";
        descriptor.engine_route = "SIMD|NEAR_SRAM_ACCUM";
        descriptor.residency_action = "WAVE_STREAM_IN->DENSITY_BUFFER_COMMIT";
        descriptor.estimated_latency_ns = 12.0;
        return descriptor;
    }

    if (request.stage_kind == "BODY_04B_POTENTIAL_REFRESH") {
        descriptor.execution_domain = "OUTER_UPDATE_RUNTIME";
        descriptor.engine_route = request.phase_b_summary.config.support_grid_mode == "BYPASS"
                                      ? "SIMD|NEAR_SRAM"
                                      : "FFT|SIMD|NEAR_SRAM";
        descriptor.residency_action =
            request.phase_b_summary.config.support_grid_mode == "BYPASS"
                ? "DENSITY_READ->PROJECTOR_STATE_COMMIT"
                : "DENSITY_READ->GRID_REFRESH->PROJECTOR_STATE_COMMIT";
        descriptor.estimated_latency_ns =
            request.phase_b_summary.config.support_grid_mode == "BYPASS" ? 14.0 : 18.0;
        return descriptor;
    }

    descriptor.execution_domain = "OUTER_UPDATE_RUNTIME";
    descriptor.engine_route = "SIMD|SCF_CONTROL";
    descriptor.residency_action = "DENSITY_MIX->HISTORY_COMMIT";
    descriptor.estimated_latency_ns = 10.0;
    return descriptor;
}

Body04StageSummary OuterUpdateRuntimeDomain::make_stage_summary(
    const Body04StageRequest& request, const DensitySummary& density) const {
    Body04StageSummary stage;
    stage.stage_kind = request.stage_kind;
    stage.completion_mode = request.completion_mode;
    stage.join_mode = request.join_mode;
    stage.input_handle = request.primary_input_object.object_handle;
    stage.output_handle = density.density_object.object_handle;
    stage.data_movement_kib = density.data_movement_kib;
    stage.detail = density.brief();
    stage.unit_occupancy.push_back(
        make_occupancy("DensityAccumulatorUnit.Reduce", 1, 8, 1));
    stage.unit_occupancy.push_back(
        make_occupancy("DensityCommitUnit.Commit", 1, 4, 1));
    stage.total_ref_cycles = sum_busy_ref_cycles(stage.unit_occupancy);
    stage.critical_unit = pick_critical_unit(stage.unit_occupancy);
    stage.flow_control = simulate_body04_pipeline(
        {make_body04_leaf_spec(
             "DensityAccumulatorUnit.Reduce",
             2,
             8,
             "DensityAccumulatorUnit.Reduce->DensityCommitUnit.Commit",
             "wave_density_reduce_fifo_not_full",
             "density_reduce_busy_or_output_hold",
             "density_partial_ready_for_commit",
             "DensityAccumulationStage.reduce_fifo",
             "DensityCommitUnit.commit_fifo",
             "DENSITY_ACCUM_DOMAIN",
             "DENSITY_REDUCE"),
         make_body04_leaf_spec(
             "DensityCommitUnit.Commit",
             1,
             4,
             "DensityCommitUnit.Commit->BODY_04A_STAGE_COMMIT",
             "density_commit_slot_free",
             "density_commit_busy_or_output_hold",
             "density_object_committed",
             "DensityCommitUnit.commit_fifo",
             "BODY_04A.stage_boundary",
             "DENSITY_COMMIT_DOMAIN",
             "DENSITY_COMMIT")},
        1,
        1,
        "BODY_04A_ISSUE->DensityAccumulatorUnit.Reduce");
    return stage;
}

Body04StageSummary OuterUpdateRuntimeDomain::make_stage_summary(
    const Body04StageRequest& request, const PotentialSummary& potential) const {
    Body04StageSummary stage;
    stage.stage_kind = request.stage_kind;
    stage.completion_mode = request.completion_mode;
    stage.join_mode = request.join_mode;
    stage.input_handle = request.primary_input_object.object_handle;
    stage.output_handle = potential.potential_object.object_handle;
    stage.data_movement_kib = potential.grid_exchange_kib;
    stage.detail = potential.brief();

    const int potential_build_cycles =
        request.phase_b_summary.config.support_grid_mode == "BYPASS" ? 9 : 13;
    stage.unit_occupancy.push_back(
        make_occupancy("PotentialFieldUnit.Build", 1, potential_build_cycles, 1));
    stage.unit_occupancy.push_back(
        make_occupancy("ProjectorStateUpdater.Update", 1, 5, 1));
    stage.total_ref_cycles = sum_busy_ref_cycles(stage.unit_occupancy);
    stage.critical_unit = pick_critical_unit(stage.unit_occupancy);
    stage.flow_control = simulate_body04_pipeline(
        {make_body04_leaf_spec(
             "PotentialFieldUnit.Build",
             1,
             potential_build_cycles,
             "PotentialFieldUnit.Build->ProjectorStateUpdater.Update",
             "potential_field_fifo_not_full",
             "potential_field_build_busy_or_output_hold",
             "potential_field_ready_for_projector_update",
             "PotentialRefreshStage.field_fifo",
             "ProjectorStateUpdater.update_fifo",
             "POTENTIAL_FIELD_DOMAIN",
             "POTENTIAL_FIELD_BUILD"),
         make_body04_leaf_spec(
             "ProjectorStateUpdater.Update",
             1,
             5,
             "ProjectorStateUpdater.Update->BODY_04B_STAGE_COMMIT",
             "projector_state_slot_free",
             "projector_state_update_busy_or_output_hold",
             "potential_and_projector_state_committed",
             "ProjectorStateUpdater.update_fifo",
             "BODY_04B.stage_boundary",
             "PROJECTOR_STATE_DOMAIN",
             "PROJECTOR_STATE_UPDATE")},
        1,
        1,
        "BODY_04B_ISSUE->PotentialFieldUnit.Build");
    return stage;
}

Body04StageSummary OuterUpdateRuntimeDomain::make_stage_summary(
    const Body04StageRequest& request, const MixingSummary& mixing) const {
    Body04StageSummary stage;
    stage.stage_kind = request.stage_kind;
    stage.completion_mode = request.completion_mode;
    stage.join_mode = request.join_mode;
    stage.input_handle = request.primary_input_object.object_handle + "/" +
                         request.secondary_input_object.object_handle;
    stage.output_handle = mixing.mixed_density_object.object_handle;
    stage.data_movement_kib = 0.0;
    stage.detail = mixing.brief();
    stage.unit_occupancy.push_back(
        make_occupancy("DensityMixerUnit.Mix", 1, 6, 1));
    stage.unit_occupancy.push_back(
        make_occupancy("ConvergenceTracker.Decide", 1, 4, 1));
    stage.total_ref_cycles = sum_busy_ref_cycles(stage.unit_occupancy);
    stage.critical_unit = pick_critical_unit(stage.unit_occupancy);
    stage.flow_control = simulate_body04_pipeline(
        {make_body04_leaf_spec(
             "DensityMixerUnit.Mix",
             1,
             6,
             "DensityMixerUnit.Mix->ConvergenceTracker.Decide",
             "mix_fifo_not_full",
             "density_mix_busy_or_output_hold",
             "mixed_density_candidate_ready",
             "MixingConvergenceStage.mix_fifo",
             "ConvergenceTracker.decision_fifo",
             "DENSITY_MIX_DOMAIN",
             "DENSITY_MIX"),
         make_body04_leaf_spec(
             "ConvergenceTracker.Decide",
             1,
             4,
             "ConvergenceTracker.Decide->BODY_04C_STAGE_EXIT",
             "convergence_slot_free",
             "convergence_decide_busy_or_output_hold",
             "scf_decision_committed",
             "ConvergenceTracker.decision_fifo",
             "BODY_05.query_boundary",
             "CONVERGENCE_GATE_DOMAIN",
             "CONVERGENCE_DECIDE")},
        1,
        1,
        "BODY_04C_ISSUE->DensityMixerUnit.Mix");
    return stage;
}

Body04LoweringPlan OuterUpdateRuntimeDomain::make_lowering_plan(
    const Body04BundleRequest& request, const Body04StageRequest& density_request,
    const Body04StageRequest& potential_request,
    const Body04StageRequest& mixing_request) const {
    Body04LoweringPlan plan;
    plan.bundle_id = request.bundle_id;
    plan.phase_family = request.phase_family;
    plan.software_family = request.software_family;
    plan.flow_family = request.flow_family;
    plan.domain_name = "OuterUpdateRuntimeDomain";
    plan.density_stage =
        make_stage_descriptor(density_request, density_output_handle(density_request));
    plan.potential_stage = make_stage_descriptor(
        potential_request, potential_output_handle(potential_request));
    plan.mixing_stage =
        make_stage_descriptor(mixing_request, mixing_output_handle(mixing_request));
    plan.total_estimated_latency_ns = plan.density_stage.estimated_latency_ns +
                                      plan.potential_stage.estimated_latency_ns +
                                      plan.mixing_stage.estimated_latency_ns;
    return plan;
}

Body04BundleSummary OuterUpdateRuntimeDomain::execute(
    const Body04BundleRequest& request) const {
    log_line(name(), "Outer-update runtime bundle begins: " + request.brief());

    const auto density_request = make_density_request(request);

    DensitySummary predicted_density;
    predicted_density.density_object.object_handle = density_output_handle(density_request);
    const auto potential_seed_request = make_potential_request(request, predicted_density);

    PotentialSummary predicted_potential;
    predicted_potential.potential_object.object_handle =
        potential_output_handle(potential_seed_request);
    const auto mixing_seed_request =
        make_mixing_request(request, predicted_density, predicted_potential);

    Body04BundleSummary summary;
    summary.bundle_id = request.bundle_id;
    summary.phase_family = request.phase_family;
    summary.software_family = request.software_family;
    summary.flow_family = request.flow_family;
    summary.lowering_plan =
        make_lowering_plan(request, density_request, potential_seed_request, mixing_seed_request);

    log_line(name(), "BODY_04 lowering plan => " + summary.lowering_plan.brief());
    log_line(name(), "BODY_04 lowering stage => " + summary.lowering_plan.density_stage.brief());
    log_line(name(), "BODY_04 lowering stage => " + summary.lowering_plan.potential_stage.brief());
    log_line(name(), "BODY_04 lowering stage => " + summary.lowering_plan.mixing_stage.brief());

    log_line(name(), "BODY_04 stage request => " + density_request.brief());
    summary.density = density_stage_.accumulate(density_request);
    summary.density_stage = make_stage_summary(density_request, summary.density);
    log_body04_stage_details(name(), summary.density_stage);

    const auto potential_request = make_potential_request(request, summary.density);
    log_line(name(), "BODY_04 stage request => " + potential_request.brief());
    summary.potential = potential_stage_.refresh(potential_request, summary.density);
    summary.potential_stage = make_stage_summary(potential_request, summary.potential);
    log_body04_stage_details(name(), summary.potential_stage);

    const auto mixing_request =
        make_mixing_request(request, summary.density, summary.potential);
    log_line(name(), "BODY_04 stage request => " + mixing_request.brief());
    summary.mixing =
        mixing_stage_.mix(mixing_request, summary.density, summary.potential);
    summary.mixing_stage = make_stage_summary(mixing_request, summary.mixing);
    log_body04_stage_details(name(), summary.mixing_stage);

    summary.bundle_data_movement_kib = summary.density_stage.data_movement_kib +
                                       summary.potential_stage.data_movement_kib +
                                       summary.mixing_stage.data_movement_kib;
    summary.continue_scf = !summary.mixing.converged;
    refresh_body04_bundle_summary(summary);

    log_line(name(), "Outer-update runtime bundle complete: " + summary.brief());
    return summary;
}

}  // namespace qebs
