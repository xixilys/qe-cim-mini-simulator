#include "episode_controller.hpp"

namespace qebs {

EpisodeController::EpisodeController(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

EpisodeControllerState EpisodeController::begin_episode(
    const EpisodeDescriptor& descriptor) const {
  sc_core::wait(3.0, sc_core::SC_NS);

  EpisodeControllerState state;
  state.workload_bucket = descriptor.workload_bucket;
  state.projector_mode = descriptor.projector_mode;
  state.cdiaghg_mode_selected = descriptor.preferred_diag_mode;

  if (descriptor.workload_bucket == "small") {
    state.fifo_ab_credit_limit = 3;
    state.fifo_bc_credit_limit = 2;
    state.fifo_cd_credit_limit = 2;
    state.resident_budget_kib = 192.0;
  } else if (descriptor.workload_bucket == "large") {
    state.fifo_ab_credit_limit = 2;
    state.fifo_bc_credit_limit = 1;
    state.fifo_cd_credit_limit = 1;
    state.resident_budget_kib = 448.0;
  } else {
    state.fifo_ab_credit_limit = 2;
    state.fifo_bc_credit_limit = 1;
    state.fifo_cd_credit_limit = 1;
    state.resident_budget_kib = 384.0;
  }

  state.estimated_resident_footprint_kib =
      8.0 * static_cast<double>(descriptor.panel_count * descriptor.panel_size) +
      4.0 * static_cast<double>(descriptor.band_batch) +
      (descriptor.projector_mode == "NC-light" ? 24.0 : 56.0);
  state.resident_fit =
      state.estimated_resident_footprint_kib <= state.resident_budget_kib;
  state.estimated_spill_kib = state.resident_fit
                                  ? 0.0
                                  : state.estimated_resident_footprint_kib -
                                        state.resident_budget_kib;
  state.spill_active = state.estimated_spill_kib > 0.0;

  if (!state.resident_fit) {
    state.cdiaghg_mode_selected = "fallback_companion";
  }

  log_line(name(), "Episode controller begins: " + descriptor.brief());
  log_line(name(), "Episode controller state => " + state.brief());
  return state;
}

void EpisodeController::observe_cluster_a(const ClusterAOutput& output,
                                          EpisodeControllerState& state) const {
  if (output.metrics.backpressure_ref_cycles >
      output.metrics.accounted_ref_cycles / 3) {
    state.controller_sync_ref_cycles += 1;
  }
}

void EpisodeController::observe_cluster_b(const ClusterBOutput& output,
                                          EpisodeControllerState& state) const {
  if (output.spill_flag) {
    state.spill_active = true;
    state.resident_fit = false;
    state.estimated_spill_kib += output.metrics.data_movement_kib * 0.25;
  }
}

void EpisodeController::observe_cluster_c(const ClusterCOutput& output,
                                          EpisodeControllerState& state) const {
  state.cdiaghg_mode_selected = output.cdiaghg_mode_selected;
}

void EpisodeController::observe_cluster_d(const ClusterDOutput& output,
                                          EpisodeControllerState& state) const {
  if (!output.episode_continue_flag) {
    state.controller_sync_ref_cycles += 1;
  }
}

bool EpisodeController::should_continue(const ClusterDOutput& output,
                                        const EpisodeDescriptor& descriptor,
                                        int inner_step) const {
  return output.episode_continue_flag &&
         (inner_step + 1) < descriptor.max_inner_steps;
}

void EpisodeController::finalize_episode(EpisodeResult& result) const {
  result.total_ref_cycles = result.cluster_a.accounted_ref_cycles +
                            result.cluster_b.accounted_ref_cycles +
                            result.cluster_c.accounted_ref_cycles +
                            result.cluster_d.accounted_ref_cycles +
                            result.controller_state.controller_sync_ref_cycles;
  result.total_backpressure_ref_cycles =
      result.cluster_a.backpressure_ref_cycles +
      result.cluster_b.backpressure_ref_cycles +
      result.cluster_c.backpressure_ref_cycles +
      result.cluster_d.backpressure_ref_cycles;
  result.total_data_movement_kib =
      result.cluster_a.data_movement_kib + result.cluster_b.data_movement_kib +
      result.cluster_c.data_movement_kib + result.cluster_d.data_movement_kib;
  result.status = result.converged_inner_loop ? "inner-loop-converged"
                                              : "max-inner-steps-reached";
  result.controller_state.spill_active =
      result.controller_state.estimated_spill_kib > 0.0;
}

}  // namespace qebs
