#include <algorithm>

#include "density_accumulator_unit.hpp"

namespace qebs {

DensityAccumulatorUnit::DensityAccumulatorUnit(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

DensityAccumStats DensityAccumulatorUnit::reduce(
    const Body04StageRequest& request) const {
  sc_core::wait(8.0, sc_core::SC_NS);

  const auto& state = request.incoming_state;
  const auto& summary = request.phase_b_summary;
  const bool is_cp2k = summary.config.software_family == "CP2K";
  const bool is_ot = summary.config.flow_family == "QS_OT";
  const bool is_vasp = summary.config.software_family == "VASP";
  const bool is_fast = summary.config.flow_family == "FAST";

  DensityAccumStats stats;
  stats.rho_out_norm = std::max(
      1e-6, 0.58 * summary.residual.updated_vector_norm + 0.12 * state.rho_norm +
                0.01 * static_cast<double>(summary.config.band_batch) +
                (is_ot ? 0.06 : (is_cp2k ? 0.05 : (is_vasp ? 0.04 : 0.0))));
  stats.occupation_checksum =
      0.50 * static_cast<double>(summary.ritz.active_vectors) +
      0.03 * static_cast<double>(summary.config.band_count) +
      0.02 * static_cast<double>(summary.config.band_batch) +
      (is_ot ? 0.25 : (is_cp2k ? 0.10 : (is_fast ? 0.16 : (is_vasp ? 0.12 : 0.0))));
  stats.accumulated_bands =
      summary.config.band_count - (is_ot ? 1 : 0) - (is_fast ? 1 : 0);
  stats.data_movement_kib =
      0.75 * static_cast<double>(summary.config.band_count * summary.config.panel_count *
                                 summary.config.panel_size) *
      (is_ot ? 1.35 : (is_cp2k ? 1.15 : (is_fast ? 1.30 : (is_vasp ? 1.22 : 1.0))));

  log_line(name(), request.stage_kind + " reduced density stats => " + stats.brief());
  return stats;
}

}  // namespace qebs
