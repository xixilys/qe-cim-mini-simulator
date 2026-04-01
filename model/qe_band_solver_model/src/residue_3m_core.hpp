#pragma once

#include "logging.hpp"
#include "systemc_compat.hpp"
#include "types.hpp"

namespace qebs {

class Residue3MCore : public sc_core::sc_module {
 public:
  explicit Residue3MCore(sc_core::sc_module_name name);
  ProjectCoeffPacket project(const EpisodeConfig& config,
                             const ResidentContextDesc& context,
                             const RowBlockWindowDesc& window,
                             const DigitStreamSlice& slice) const;
  BackprojectRowPacket backproject(const EpisodeConfig& config,
                                   const ResidentContextDesc& context,
                                   const RowBlockWindowDesc& window,
                                   const ProjectCoeffPacket& coeff) const;
};

}  // namespace qebs
