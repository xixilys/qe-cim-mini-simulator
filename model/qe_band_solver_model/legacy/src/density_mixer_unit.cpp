#include <algorithm>

#include "density_mixer_unit.hpp"

namespace qebs {

DensityMixerUnit::DensityMixerUnit(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

DensityMixStats DensityMixerUnit::mix_density(const Body04StageRequest& request,
                                              const DensitySummary& density,
                                              const PotentialSummary& potential) const {
  sc_core::wait(6.0, sc_core::SC_NS);

  const auto& state = request.incoming_state;
  const auto& summary = request.phase_b_summary;
  const bool is_cp2k = summary.config.software_family == "CP2K";
  const bool is_ot = summary.config.flow_family == "QS_OT";
  const bool is_vasp = summary.config.software_family == "VASP";
  const bool is_fast = summary.config.flow_family == "FAST";

  DensityMixStats stats;
  stats.density_delta =
      0.18 / static_cast<double>(summary.config.scf_iteration) +
      0.015 * summary.residual.residual_norm +
      0.005 * (1.0 - potential.projector_refresh_score) +
      (is_ot ? 0.015
             : (is_cp2k ? 0.008 : (is_fast ? 0.011 : (is_vasp ? 0.006 : 0.0))));
  stats.mixed_rho_norm = std::max(1e-6, state.rho_norm - stats.density_delta);

  log_line(name(), request.stage_kind + " mixed density stats => " + stats.brief());
  return stats;
}

}  // namespace qebs
