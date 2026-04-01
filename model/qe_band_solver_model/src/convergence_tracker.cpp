#include <cmath>

#include "convergence_tracker.hpp"

namespace qebs {

namespace {

std::string mixing_prefix(const std::string& software_family,
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

}  // namespace

ConvergenceTracker::ConvergenceTracker(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

ConvergenceDecision ConvergenceTracker::decide(const Body04StageRequest& request,
                                               const DensitySummary& density,
                                               const PotentialSummary& potential,
                                               const DensityMixStats& mix_stats) const {
  sc_core::wait(4.0, sc_core::SC_NS);

  const auto& state = request.incoming_state;
  const auto& summary = request.phase_b_summary;
  const bool is_cp2k = summary.config.software_family == "CP2K";
  const bool is_ot = summary.config.flow_family == "QS_OT";
  const bool is_vasp = summary.config.software_family == "VASP";
  const bool is_fast = summary.config.flow_family == "FAST";
  const std::string prefix =
      mixing_prefix(summary.config.software_family, summary.config.flow_family);

  ConvergenceDecision decision;
  decision.history_object.object_handle =
      prefix + "_scf_hist_iter_" + std::to_string(summary.config.scf_iteration);
  decision.history_object.version = summary.config.scf_iteration;
  decision.history_object.resident_buffer_tag = 420 + summary.config.scf_iteration;
  decision.history_object.producer_body = "BODY_04C";
  decision.history_object.validity_scope = "full-run";
  decision.energy_delta = std::abs(summary.ritz.et - state.total_energy) *
                          (is_ot ? 0.24
                                 : (is_fast ? 0.27 : (is_vasp ? 0.28 : 0.30)));
  decision.history_depth = summary.config.scf_iteration;
  decision.converged = mix_stats.density_delta <=
                           (is_ot ? 0.085
                                  : (is_fast ? 0.080 : (is_vasp ? 0.078 : 0.075))) &&
                       decision.energy_delta <=
                           (is_cp2k ? 0.24 : (is_vasp ? 0.22 : 0.18)) &&
                       density.rho_out_norm <=
                           (is_cp2k ? 0.55 : (is_vasp ? 0.50 : 0.43));

  log_line(name(), request.stage_kind + " convergence decision => " + decision.brief());
  return decision;
}

}  // namespace qebs
