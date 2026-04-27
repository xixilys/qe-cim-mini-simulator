#include <algorithm>

#include "preconditioned_update_vector.hpp"

namespace qebs {

PreconditionedUpdateVector::PreconditionedUpdateVector(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

Body10PrecondStats PreconditionedUpdateVector::apply(
    const Body10StageRequest& request) const {
  sc_core::wait(5.0, sc_core::SC_NS);

  Body10PrecondStats stats;
  stats.active_blocks =
      std::max(2, request.phase_b_summary.config.panel_count - 1);
  const double total_move_kib =
      0.22 * static_cast<double>(request.phase_b_summary.config.band_count *
                                 request.phase_b_summary.config.panel_count *
                                 request.phase_b_summary.config.panel_size);
  stats.block_update_norm = std::max(
      1e-6,
      0.45 * request.phase_b_summary.residual.updated_vector_norm +
          0.08 * request.phase_b_summary.reduced.closure_score +
          0.02 * static_cast<double>(stats.active_blocks));
  stats.data_movement_kib = 0.35 * total_move_kib;

  log_line(name(), request.stage_kind + " preconditioned-update stats => " +
                       stats.brief());
  return stats;
}

}  // namespace qebs
