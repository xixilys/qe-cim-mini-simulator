#include <algorithm>

#include "orthogonalize_unit.hpp"

namespace qebs {

OrthogonalizeUnit::OrthogonalizeUnit(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

Body10OrthoStats OrthogonalizeUnit::project(
    const Body10StageRequest& request, const Body10PrecondSummary& precond) const {
  sc_core::wait(4.0, sc_core::SC_NS);

  const int iter = request.incoming_state.scf_iteration;
  const double total_move_kib =
      0.22 * static_cast<double>(request.phase_b_summary.config.band_count *
                                 request.phase_b_summary.config.panel_count *
                                 request.phase_b_summary.config.panel_size);

  Body10OrthoStats stats;
  stats.active_blocks = precond.active_blocks;
  stats.orthogonality_score = std::min(
      0.995,
      0.71 +
          0.03 * static_cast<double>(request.phase_b_summary.config.max_inner_steps) +
          0.02 * static_cast<double>(iter) +
          0.01 * static_cast<double>(stats.active_blocks));
  stats.data_movement_kib = 0.65 * total_move_kib;

  log_line(name(), request.stage_kind + " orthogonalize stats => " +
                       stats.brief());
  return stats;
}

}  // namespace qebs
