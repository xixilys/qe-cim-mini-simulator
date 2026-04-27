#include "residue_3m_core.hpp"

namespace qebs {

Residue3MCore::Residue3MCore(sc_core::sc_module_name name)
    : sc_core::sc_module(name) {}

ProjectCoeffPacket Residue3MCore::project(const EpisodeConfig& config,
                                          const ResidentContextDesc& context,
                                          const RowBlockWindowDesc& window,
                                          const DigitStreamSlice& slice) const {
  sc_core::wait(6.0, sc_core::SC_NS);

  ProjectCoeffPacket coeff;
  coeff.panel_id = slice.panel_id;
  coeff.resident_context_id = context.resident_context_id;
  coeff.resident_generation = context.generation;
  coeff.row_block_id = window.row_block_id;
  coeff.coeff_energy =
      slice.magnitude_checksum * (0.72 + 0.02 * static_cast<double>(config.scf_iteration));
  coeff.coeff_condition =
      1.0 / (1.0 + static_cast<double>(window.row_block_id + context.column_group_count));

  log_line(name(), "Residue3MCore PROJECT produced " + coeff.brief());
  return coeff;
}

BackprojectRowPacket Residue3MCore::backproject(const EpisodeConfig& config,
                                                const ResidentContextDesc& context,
                                                const RowBlockWindowDesc& window,
                                                const ProjectCoeffPacket& coeff) const {
  sc_core::wait(6.0, sc_core::SC_NS);

  BackprojectRowPacket row;
  row.panel_id = coeff.panel_id;
  row.resident_context_id = context.resident_context_id;
  row.resident_generation = context.generation;
  row.row_block_id = window.row_block_id;
  row.row_energy = coeff.coeff_energy * (0.83 + 0.01 * static_cast<double>(config.band_count));
  row.overlap_energy = coeff.coeff_condition * (0.91 + 0.03 * window.row_block_id);

  log_line(name(), "Residue3MCore BACKPROJECT produced " + row.brief());
  return row;
}

}  // namespace qebs
