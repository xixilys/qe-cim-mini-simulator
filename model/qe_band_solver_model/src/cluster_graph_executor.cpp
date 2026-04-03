#include "cluster_graph_executor.hpp"

namespace qebs {

namespace {

void accumulate_metrics(ClusterMetrics& dst, const ClusterMetrics& src) {
  dst.cluster_name = src.cluster_name;
  dst.invocations += src.invocations;
  dst.accounted_ref_cycles += src.accounted_ref_cycles;
  dst.backpressure_ref_cycles += src.backpressure_ref_cycles;
  dst.data_movement_kib += src.data_movement_kib;
  dst.dominant_resource = src.dominant_resource;
  dst.detail = src.detail;
}

}  // namespace

ClusterGraphExecutor::ClusterGraphExecutor(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      cluster_a_(sc_core::sc_module_name("cluster_a_operator_sweep")),
      cluster_b_(sc_core::sc_module_name("cluster_b_reduced_build")),
      cluster_c_(sc_core::sc_module_name("cluster_c_hardware_diag")),
      cluster_d_(sc_core::sc_module_name("cluster_d_refresh_residual")) {}

EpisodeResult ClusterGraphExecutor::run_episode(
    const EpisodeDescriptor& descriptor,
    const EpisodeController& controller) const {
  EpisodeResult result;
  result.descriptor = descriptor;
  result.controller_state = controller.begin_episode(descriptor);
  result.status = "running";

  for (int inner_step = 0; inner_step < descriptor.max_inner_steps; ++inner_step) {
    const auto a_out = cluster_a_.run({descriptor, inner_step});
    controller.observe_cluster_a(a_out, result.controller_state);
    accumulate_metrics(result.cluster_a, a_out.metrics);
    result.resident_context = a_out.resident_context;
    result.lcw_words_issued += a_out.lcw_words_issued;
    result.row_blocks_processed += a_out.row_blocks_processed;

    const auto b_out = cluster_b_.run({descriptor, inner_step, a_out.partials});
    controller.observe_cluster_b(b_out, result.controller_state);
    accumulate_metrics(result.cluster_b, b_out.metrics);
    result.full_hs = b_out.full_hs;
    result.reduced = b_out.reduced;

    const auto c_out = cluster_c_.run(
        {descriptor, inner_step, b_out.reduced, result.controller_state});
    controller.observe_cluster_c(c_out, result.controller_state);
    accumulate_metrics(result.cluster_c, c_out.metrics);
    result.diag_solution = c_out.diag_solution;
    result.crossover_margin = c_out.crossover_margin;

    const auto d_out = cluster_d_.run(
        {descriptor, inner_step, c_out.diag_solution, result.controller_state});
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
