#include "vector_diag_companion.hpp"

namespace qebs {

VectorDiagCompanion::VectorDiagCompanion(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

std::pair<RitzResult, ResidualPacket> VectorDiagCompanion::solve_and_update(
    const EpisodeConfig& config, const ReducedMatrices& reduced, int inner_step) const {
  sc_core::wait(7.0, sc_core::SC_NS);

  RitzResult ritz;
  ritz.active_vectors = config.band_count < 4 ? config.band_count : 4;
  ritz.et = -12.0 + 0.12 * config.scf_iteration - 0.02 * reduced.h_small;
  ritz.evc_norm = 0.6 + 0.4 * reduced.closure_score;
  for (int i = 0; i < 3; ++i) {
    ritz.eigenvalues.push_back(ritz.et + 0.01 * static_cast<double>(i));
  }

  ResidualPacket residual;
  residual.residual_norm = 0.72 / static_cast<double>(inner_step + 1) +
                           0.02 * static_cast<double>(config.scf_iteration - 1);
  residual.updated_vector_norm = 0.55 * ritz.evc_norm + 0.25 * residual.residual_norm;
  residual.episode_done = residual.residual_norm <= 0.24 ||
                          (inner_step + 1) >= config.max_inner_steps;
  residual.updates_applied = inner_step + 1;

  log_line(name(), "Vector/diag companion produced et/evc + residual update step " +
                       std::to_string(inner_step + 1));
  return {ritz, residual};
}

}  // namespace qebs
