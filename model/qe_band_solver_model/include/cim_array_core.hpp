#pragma once

#include "coefficient_accumulator.hpp"
#include "logging.hpp"
#include "residue_3m_core.hpp"
#include "row_merge_tree.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class CIMArrayCore : public sc_core::sc_module {
 public:
  explicit CIMArrayCore(sc_core::sc_module_name name);
  ProjectCoeffPacket project(const EpisodeConfig& config,
                             const ResidentContextDesc& context,
                             const RowBlockWindowDesc& window,
                             const DigitStreamSlice& slice) const;
  PartialHS backproject(const EpisodeConfig& config,
                        const ResidentContextDesc& context,
                        const RowBlockWindowDesc& window,
                        const ProjectCoeffPacket& coeff) const;

 private:
  Residue3MCore residue_3m_core_;
  CoefficientAccumulator coefficient_accumulator_;
  RowMergeTree row_merge_tree_;
};

}  // namespace qebs
