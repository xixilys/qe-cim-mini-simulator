#include "cim_array_core.hpp"

namespace qebs {

CIMArrayCore::CIMArrayCore(sc_core::sc_module_name name)
    : sc_core::sc_module(name),
      residue_3m_core_(sc_core::sc_module_name("residue_3m_core")),
      coefficient_accumulator_(sc_core::sc_module_name("coefficient_accumulator")),
      row_merge_tree_(sc_core::sc_module_name("row_merge_tree")) {}

ProjectCoeffPacket CIMArrayCore::project(const EpisodeConfig& config,
                                         const ResidentContextDesc& context,
                                         const RowBlockWindowDesc& window,
                                         const DigitStreamSlice& slice) const {
  auto coeff = residue_3m_core_.project(config, context, window, slice);
  auto accumulated = coefficient_accumulator_.accumulate(config, window, coeff);
  log_line(name(), "CIMArrayCore completed PROJECT for panel=" +
                       std::to_string(slice.panel_id) +
                       ", row_block=" + std::to_string(window.row_block_id));
  return accumulated;
}

PartialHS CIMArrayCore::backproject(const EpisodeConfig& config,
                                    const ResidentContextDesc& context,
                                    const RowBlockWindowDesc& window,
                                    const ProjectCoeffPacket& coeff) const {
  auto row = residue_3m_core_.backproject(config, context, window, coeff);
  auto partial = row_merge_tree_.merge(config, window, row);
  log_line(name(), "CIMArrayCore completed BACKPROJECT for panel=" +
                       std::to_string(coeff.panel_id) +
                       ", row_block=" + std::to_string(window.row_block_id));
  return partial;
}

}  // namespace qebs
