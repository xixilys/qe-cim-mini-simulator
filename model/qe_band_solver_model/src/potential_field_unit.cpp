#include <algorithm>

#include "potential_field_unit.hpp"

namespace qebs {

PotentialFieldUnit::PotentialFieldUnit(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

PotentialFieldStats PotentialFieldUnit::build(const Body04StageRequest& request,
                                              const DensitySummary& density) const {
  sc_core::wait(9.0, sc_core::SC_NS);

  const auto& summary = request.phase_b_summary;
  const bool is_cp2k = summary.config.software_family == "CP2K";
  const bool is_ot = summary.config.flow_family == "QS_OT";
  const bool is_vasp = summary.config.software_family == "VASP";
  const bool support_grid = summary.config.support_grid_mode != "BYPASS";

  PotentialFieldStats stats;
  stats.potential_norm = std::max(
      1e-6, 0.82 * density.rho_out_norm +
                0.04 * static_cast<double>(summary.config.panel_count) +
                0.02 * static_cast<double>(summary.config.band_batch) +
                (is_ot ? 0.07 : (is_cp2k ? 0.06 : (is_vasp ? 0.05 : 0.0))));
  stats.grid_exchange_kib =
      (0.60 * density.data_movement_kib +
       8.0 * static_cast<double>(summary.config.panel_count)) *
      (is_ot ? 1.20 : (is_cp2k ? 1.10 : (is_vasp ? 1.18 : 1.0))) *
      (support_grid ? 1.18 : 1.0);

  log_line(name(), request.stage_kind + " built potential field stats => " + stats.brief());
  return stats;
}

}  // namespace qebs
