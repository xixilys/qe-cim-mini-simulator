#include "history_integrator.hpp"

namespace qebs {

HistoryIntegrator::HistoryIntegrator(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

Body10HistoryStats HistoryIntegrator::integrate(
    const Body10StageRequest& request, const Body10OrthoSummary& ortho) const {
  sc_core::wait(2.0, sc_core::SC_NS);

  Body10HistoryStats stats;
  stats.accepted = ortho.orthogonality_score >= 0.78;
  stats.history_depth = request.incoming_state.scf_iteration;

  log_line(name(), request.stage_kind + " integrated history stats => " +
                       stats.brief());
  return stats;
}

}  // namespace qebs
