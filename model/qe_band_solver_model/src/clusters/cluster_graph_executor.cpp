#include <array>
#include <string>
#include <utility>
#include <vector>

#include "cluster_graph_frontdoor_sequence.hpp"
#include "cluster_graph_executor.hpp"
#include "cluster_factory.hpp"
#include "cluster_a_operator_sweep.hpp"
#include "cluster_b_reduced_build.hpp"
#include "cluster_c_hardware_diag.hpp"
#include "cluster_d_refresh_residual.hpp"
#include "logging.hpp"

namespace qebs {

namespace {

struct GraphExecutionPlan {
  std::vector<std::string> post_a_tokens;
  std::string execution_sequence;
  std::string source;
};

void accumulate_metrics(ClusterMetrics& dst, const ClusterMetrics& src) {
  dst.cluster_name = src.cluster_name;
  dst.invocations += src.invocations;
  dst.accounted_ref_cycles += src.accounted_ref_cycles;
  dst.backpressure_ref_cycles += src.backpressure_ref_cycles;
  dst.data_movement_kib += src.data_movement_kib;
  dst.dominant_resource = src.dominant_resource;
  dst.detail = src.detail;
}

ClusterDOutput make_graph_frontdoor_cluster_d_bypass(
    const EpisodeDescriptor& descriptor,
    int inner_step,
    const ClusterCOutput& c_out,
    const EpisodeControllerState& controller_state) {
  sc_core::wait(1.0 + static_cast<double>(descriptor.graph_flow_count), sc_core::SC_NS);
  ClusterDOutput output;
  output.p_next_object.object_handle =
      "graph_frontdoor_bypass_p_next_" + std::to_string(descriptor.scf_iteration) +
      "_step_" + std::to_string(inner_step + 1);
  output.p_next_object.version = descriptor.scf_iteration;
  output.p_next_object.resident_buffer_tag = 700 + inner_step;
  output.p_next_object.producer_body = "GraphFrontdoorBypass";
  output.p_next_object.validity_scope = "episode-window";
  output.residual_norm =
      0.28 + 0.03 * static_cast<double>(c_out.diag_solution.fallback_used ? 1 : 0) -
      0.04 * static_cast<double>(inner_step);
  output.updated_vector_norm =
      0.68 * c_out.diag_solution.coeff_norm + 0.20 * output.residual_norm;
  output.episode_continue_flag =
      output.residual_norm > 0.24 && (inner_step + 1) < descriptor.max_inner_steps;
  output.metrics.cluster_name = "ClusterDBypass";
  output.metrics.invocations = 1;
  output.metrics.accounted_ref_cycles = 1 + descriptor.graph_flow_count;
  output.metrics.backpressure_ref_cycles = controller_state.spill_active ? 2 : 0;
  output.metrics.data_movement_kib = c_out.diag_solution.emitted_kib * 0.25;
  output.metrics.dominant_resource = "GraphFrontdoor.RefreshBypass";
  output.metrics.detail = "cluster_d bypassed because graph_has_refresh_unit=false";
  return output;
}

ClusterBOutput make_graph_frontdoor_cluster_b_bypass(
    const EpisodeDescriptor& descriptor,
    int inner_step,
    const ClusterAOutput& a_out) {
  sc_core::wait(1.0 + static_cast<double>(descriptor.graph_flow_count), sc_core::SC_NS);
  ClusterBOutput output;
  output.full_hs.episode_id = descriptor.episode_id;
  output.full_hs.aggregated_panels = static_cast<int>(a_out.panels.size());
  double h_total = 0.0;
  double s_total = 0.0;
  for (const auto& partial : a_out.partials) {
    h_total += partial.h_contrib;
    s_total += partial.s_contrib;
  }
  output.full_hs.h_total = h_total;
  output.full_hs.s_total = s_total;
  output.full_hs.locality_score = 0.55 + 0.03 * static_cast<double>(a_out.partials.size());
  output.reduced.reduced_dim = std::max(2, std::min(descriptor.band_batch, static_cast<int>(a_out.partials.size())));
  output.reduced.h_small = h_total;
  output.reduced.s_small = s_total;
  output.reduced.closure_score = 0.62 - 0.04 * static_cast<double>(inner_step);
  output.spill_flag = false;
  output.metrics.cluster_name = "ClusterBBypass";
  output.metrics.invocations = 1;
  output.metrics.accounted_ref_cycles = 1 + descriptor.graph_flow_count;
  output.metrics.backpressure_ref_cycles = 0;
  output.metrics.data_movement_kib = 0.25 * static_cast<double>(a_out.partials.size());
  output.metrics.dominant_resource = "GraphFrontdoor.ReductionBypass";
  output.metrics.detail = "cluster_b bypassed because graph_has_reduction_unit=false";
  return output;
}

ClusterCOutput make_graph_frontdoor_cluster_c_bypass(
    const EpisodeDescriptor& descriptor,
    int inner_step,
    const ClusterBOutput& b_out,
    const EpisodeControllerState& controller_state) {
  sc_core::wait(1.0 + static_cast<double>(descriptor.graph_flow_count), sc_core::SC_NS);
  ClusterCOutput output;
  output.cdiaghg_mode_selected =
      descriptor.graph_has_vector_diag_companion ? "fallback_companion" : "graph_frontdoor_diag_stub";
  output.crossover_margin = 0.0;
  output.diag_solution.diag_dim_n = std::max(1, b_out.reduced.reduced_dim);
  output.diag_solution.eigenpair_count = std::max(1, std::min(descriptor.band_batch, b_out.reduced.reduced_dim));
  output.diag_solution.lambda_base = -42.0 + 0.2 * static_cast<double>(inner_step);
  output.diag_solution.coeff_norm = 0.7;
  output.diag_solution.condition_estimate = 1.10 + 0.03 * static_cast<double>(inner_step);
  output.diag_solution.residual_visibility_score = 0.35;
  output.diag_solution.emitted_kib = 0.125 * static_cast<double>(output.diag_solution.diag_dim_n);
  output.diag_solution.fallback_used = descriptor.graph_has_vector_diag_companion;
  output.diag_solution.source_domain = output.cdiaghg_mode_selected;
  output.metrics.cluster_name = "ClusterCBypass";
  output.metrics.invocations = 1;
  output.metrics.accounted_ref_cycles = 1 + descriptor.graph_flow_count;
  output.metrics.backpressure_ref_cycles = controller_state.spill_active ? 2 : 0;
  output.metrics.data_movement_kib = output.diag_solution.emitted_kib;
  output.metrics.dominant_resource = "GraphFrontdoor.DiagBypass";
  output.metrics.detail = "cluster_c bypassed because graph_has_diag_unit=false";
  return output;
}

char stage_id_for_token(const std::string& token) {
  if (token == "B" || token == "B_bypass") {
    return 'B';
  }
  if (token == "C" || token == "C_bypass") {
    return 'C';
  }
  if (token == "D" || token == "D_bypass") {
    return 'D';
  }
  return '\0';
}

std::vector<std::string> default_graph_post_a_tokens(
    const EpisodeDescriptor& descriptor) {
  return {
      descriptor.graph_has_reduction_unit ? "B" : "B_bypass",
      descriptor.graph_has_diag_unit ? "C" : "C_bypass",
      descriptor.graph_has_refresh_unit ? "D" : "D_bypass",
  };
}

std::string join_execution_sequence(const std::vector<std::string>& post_a_tokens) {
  std::string sequence = "A";
  for (const auto& token : post_a_tokens) {
    sequence += ">";
    sequence += token;
  }
  return sequence;
}

GraphExecutionPlan build_graph_execution_plan(const EpisodeDescriptor& descriptor) {
  auto make_fallback_plan = [&descriptor]() {
    GraphExecutionPlan fallback;
    fallback.post_a_tokens = default_graph_post_a_tokens(descriptor);
    fallback.execution_sequence = join_execution_sequence(fallback.post_a_tokens);
    fallback.source = "fallback_default";
    return fallback;
  };

  const auto raw_tokens =
      graph_frontdoor::split_cluster_sequence(
          descriptor.graph_resolved_cluster_sequence);
  if (raw_tokens.empty()) {
    return make_fallback_plan();
  }

  std::array<bool, 3> seen = {false, false, false};
  int last_stage_rank = -1;
  bool saw_a = false;
  std::vector<std::string> post_a_tokens;
  for (const auto& raw_token : raw_tokens) {
    if (raw_token == "A") {
      if (saw_a || !post_a_tokens.empty()) {
        return make_fallback_plan();
      }
      saw_a = true;
      continue;
    }

    const char stage_id = stage_id_for_token(raw_token);
    if (stage_id == '\0') {
      return make_fallback_plan();
    }
    const int stage_rank = static_cast<int>(stage_id - 'B');
    if (stage_rank < 0 || stage_rank >= static_cast<int>(seen.size()) ||
        stage_rank <= last_stage_rank || seen[stage_rank]) {
      return make_fallback_plan();
    }
    seen[stage_rank] = true;
    last_stage_rank = stage_rank;
    post_a_tokens.push_back(raw_token);
  }

  if (post_a_tokens.size() != 3 || !seen[0] || !seen[1] || !seen[2]) {
    return make_fallback_plan();
  }

  GraphExecutionPlan plan;
  plan.post_a_tokens = std::move(post_a_tokens);
  plan.execution_sequence = join_execution_sequence(plan.post_a_tokens);
  plan.source = "resolved_cluster_sequence";
  return plan;
}

void apply_cluster_b_output(EpisodeResult& result,
                            const EpisodeController& controller,
                            const ClusterBOutput& output) {
  controller.observe_cluster_b(output, result.controller_state);
  accumulate_metrics(result.cluster_b, output.metrics);
  result.full_hs = output.full_hs;
  result.reduced = output.reduced;
}

void apply_cluster_c_output(EpisodeResult& result,
                            const EpisodeController& controller,
                            const ClusterCOutput& output) {
  controller.observe_cluster_c(output, result.controller_state);
  accumulate_metrics(result.cluster_c, output.metrics);
  result.diag_solution = output.diag_solution;
  result.crossover_margin = output.crossover_margin;
}

void apply_cluster_d_output(EpisodeResult& result,
                            const EpisodeController& controller,
                            const ClusterDOutput& output,
                            int inner_step) {
  controller.observe_cluster_d(output, result.controller_state);
  accumulate_metrics(result.cluster_d, output.metrics);
  result.p_next_object = output.p_next_object;
  result.residual_norm = output.residual_norm;
  result.updated_vector_norm = output.updated_vector_norm;
  result.completed_inner_steps = inner_step + 1;
}

EpisodeResult run_episode_graph_frontdoor(
    const EpisodeDescriptor& descriptor,
    const EpisodeController& controller,
    ClusterWrapper* cluster_a,
    ClusterWrapper* cluster_b,
    ClusterWrapper* cluster_c,
    ClusterWrapper* cluster_d) {
  EpisodeResult result;
  result.descriptor = descriptor;
  result.controller_state = controller.begin_episode(descriptor);
  const auto execution_plan = build_graph_execution_plan(descriptor);
  result.graph_executed_cluster_sequence = execution_plan.execution_sequence;
  result.graph_execution_plan_source = execution_plan.source;
  result.status = "running";

  for (int inner_step = 0; inner_step < descriptor.max_inner_steps; ++inner_step) {
    const auto a_out = cluster_a->run_a({descriptor, inner_step});
    controller.observe_cluster_a(a_out, result.controller_state);
    accumulate_metrics(result.cluster_a, a_out.metrics);
    result.resident_context = a_out.resident_context;
    result.lcw_words_issued += a_out.lcw_words_issued;
    result.row_blocks_processed += a_out.row_blocks_processed;

    ClusterBOutput b_out;
    ClusterCOutput c_out;
    ClusterDOutput d_out;

    for (const auto& token : execution_plan.post_a_tokens) {
      if (token == "B") {
        b_out = cluster_b->run_b({descriptor, inner_step, a_out.partials});
        apply_cluster_b_output(result, controller, b_out);
      } else if (token == "B_bypass") {
        b_out = make_graph_frontdoor_cluster_b_bypass(descriptor, inner_step, a_out);
        apply_cluster_b_output(result, controller, b_out);
      } else if (token == "C") {
        c_out = cluster_c->run_c(
            {descriptor, inner_step, b_out.reduced, result.controller_state});
        apply_cluster_c_output(result, controller, c_out);
      } else if (token == "C_bypass") {
        c_out = make_graph_frontdoor_cluster_c_bypass(
            descriptor, inner_step, b_out, result.controller_state);
        apply_cluster_c_output(result, controller, c_out);
      } else if (token == "D") {
        d_out = cluster_d->run_d(
            {descriptor, inner_step, c_out.diag_solution, result.controller_state});
        apply_cluster_d_output(result, controller, d_out, inner_step);
      } else if (token == "D_bypass") {
        d_out = make_graph_frontdoor_cluster_d_bypass(
            descriptor, inner_step, c_out, result.controller_state);
        apply_cluster_d_output(result, controller, d_out, inner_step);
      }
    }

    if (!controller.should_continue(d_out, descriptor, inner_step)) {
      result.converged_inner_loop = true;
      break;
    }
  }

  controller.finalize_episode(result);
  return result;
}

}  // namespace

ClusterGraphExecutor::ClusterGraphExecutor(sc_core::sc_module_name name, const ArchitectureConfig& config)
    : sc_core::sc_module(name),
      config_(config) {
  initialize_clusters();
  log_line(std::string(name), "ClusterGraphExecutor initialized with " + std::to_string(config.cluster_count()) + " clusters");
}

ClusterGraphExecutor::ClusterGraphExecutor(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      config_(ArchitectureConfig::create_default()) {
  initialize_clusters();
  log_line(std::string(name), "ClusterGraphExecutor initialized with default configuration");
}

void ClusterGraphExecutor::initialize_clusters() {
  for (size_t i = 0; i < config_.clusters.size(); ++i) {
    const auto& cluster_config = config_.clusters[i];
    
    if (!cluster_config.enabled) {
      continue;
    }
    
    std::string cluster_name = cluster_config.cluster_id.empty() 
        ? ClusterFactory::get_default_name(cluster_config.type, static_cast<int>(i))
        : cluster_config.cluster_id;
    
    sc_core::sc_module* module = ClusterFactory::create_cluster(
        cluster_config, 
        sc_core::sc_module_name(cluster_name.c_str()));
    
    std::unique_ptr<ClusterWrapper> wrapper;
    switch (cluster_config.type) {
      case ClusterType::OPERATOR_SWEEP:
        wrapper = std::make_unique<ClusterAWrapper>(
            static_cast<ClusterAOperatorSweep*>(module),
            cluster_config.type,
            cluster_name);
        break;
      case ClusterType::REDUCED_BUILD:
        wrapper = std::make_unique<ClusterBWrapper>(
            static_cast<ClusterBReducedBuild*>(module),
            cluster_config.type,
            cluster_name);
        break;
      case ClusterType::HARDWARE_DIAG:
        wrapper = std::make_unique<ClusterCWrapper>(
            static_cast<ClusterCHardwareDiag*>(module),
            cluster_config.type,
            cluster_name);
        break;
      case ClusterType::REFRESH_RESIDUAL:
        wrapper = std::make_unique<ClusterDWrapper>(
            static_cast<ClusterDRefreshResidual*>(module),
            cluster_config.type,
            cluster_name);
        break;
    }
    
    if (wrapper) {
      clusters_.push_back(std::move(wrapper));
    }
  }
}

ClusterWrapper* ClusterGraphExecutor::find_cluster_by_type(ClusterType type) const {
  for (const auto& cluster : clusters_) {
    if (cluster->get_type() == type) {
      return cluster.get();
    }
  }
  return nullptr;
}

EpisodeResult ClusterGraphExecutor::run_episode(
    const EpisodeDescriptor& descriptor,
    const EpisodeController& controller) const {
  
  ClusterWrapper* cluster_a = find_cluster_by_type(ClusterType::OPERATOR_SWEEP);
  ClusterWrapper* cluster_b = find_cluster_by_type(ClusterType::REDUCED_BUILD);
  ClusterWrapper* cluster_c = find_cluster_by_type(ClusterType::HARDWARE_DIAG);
  ClusterWrapper* cluster_d = find_cluster_by_type(ClusterType::REFRESH_RESIDUAL);
  
  if (!cluster_a) {
    EpisodeResult error_result;
    error_result.descriptor = descriptor;
    error_result.status = "error_missing_cluster_a";
    return error_result;
  }
  
  bool has_fusion = false;
  for (const auto& cfg : config_.clusters) {
    if (!cfg.fusion_group.empty() && cfg.enabled) {
      has_fusion = true;
      break;
    }
  }
  
  if (has_fusion && cluster_c && !cluster_b) {
    cluster_b = cluster_c;
  }
  
  if (!cluster_b || !cluster_c) {
    EpisodeResult error_result;
    error_result.descriptor = descriptor;
    error_result.status = "error_missing_cluster_b_or_c";
    return error_result;
  }
  
  if (!cluster_d) {
    log_line(name(), "Warning: Cluster D (REFRESH_RESIDUAL) not found, using fallback");
  }
  
  if (!descriptor.graph_frontdoor_mode.empty()) {
    return run_episode_graph_frontdoor(
        descriptor,
        controller,
        cluster_a,
        cluster_b,
        cluster_c,
        cluster_d);
  }
  EpisodeResult result;
  result.descriptor = descriptor;
  result.controller_state = controller.begin_episode(descriptor);
  result.status = "running";

  for (int inner_step = 0; inner_step < descriptor.max_inner_steps; ++inner_step) {
    const auto a_out = cluster_a->run_a({descriptor, inner_step});
    controller.observe_cluster_a(a_out, result.controller_state);
    accumulate_metrics(result.cluster_a, a_out.metrics);
    result.resident_context = a_out.resident_context;
    result.lcw_words_issued += a_out.lcw_words_issued;
    result.row_blocks_processed += a_out.row_blocks_processed;

    const bool use_reduction_cluster =
        descriptor.graph_frontdoor_mode.empty() || descriptor.graph_has_reduction_unit;
    const auto b_out = use_reduction_cluster
                           ? cluster_b->run_b({descriptor, inner_step, a_out.partials})
                           : make_graph_frontdoor_cluster_b_bypass(descriptor, inner_step, a_out);
    controller.observe_cluster_b(b_out, result.controller_state);
    accumulate_metrics(result.cluster_b, b_out.metrics);
    result.full_hs = b_out.full_hs;
    result.reduced = b_out.reduced;

    const bool use_diag_cluster =
        descriptor.graph_frontdoor_mode.empty() || descriptor.graph_has_diag_unit;
    const auto c_out = use_diag_cluster
                           ? cluster_c->run_c(
                                 {descriptor, inner_step, b_out.reduced, result.controller_state})
                           : make_graph_frontdoor_cluster_c_bypass(
                                 descriptor, inner_step, b_out, result.controller_state);
    controller.observe_cluster_c(c_out, result.controller_state);
    accumulate_metrics(result.cluster_c, c_out.metrics);
    result.diag_solution = c_out.diag_solution;
    result.crossover_margin = c_out.crossover_margin;

    const bool use_refresh_cluster =
        descriptor.graph_frontdoor_mode.empty() || descriptor.graph_has_refresh_unit;
    const auto d_out = use_refresh_cluster
                           ? cluster_d->run_d(
                                 {descriptor, inner_step, c_out.diag_solution, result.controller_state})
                           : make_graph_frontdoor_cluster_d_bypass(
                                 descriptor, inner_step, c_out, result.controller_state);
    controller.observe_cluster_d(d_out, result.controller_state);
    accumulate_metrics(result.cluster_d, d_out.metrics);
    result.p_next_object = d_out.p_next_object;
    result.residual_norm = d_out.residual_norm;
    result.updated_vector_norm = d_out.updated_vector_norm;
    result.completed_inner_steps = inner_step + 1;

    if (!controller.should_continue(d_out, descriptor, inner_step)) {
      result.converged_inner_loop = true;
      break;
    }
  }

  controller.finalize_episode(result);
  return result;
}

}  // namespace qebs
